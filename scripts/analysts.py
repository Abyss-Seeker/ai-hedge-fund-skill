"""analysts.py — 19 个投资分析 agent 的纯规则实现

一比一移植自 virattt/ai-hedge-fund 原项目。
每个 agent 对应原项目 src/agents/{name}.py 的量化评分逻辑（不含 LLM 调用）。

函数签名统一:
    def xxx_agent(ticker, metrics, line_items, market_cap, prices=None, news=None) -> dict
    返回 {"signal": "bullish|bearish|neutral", "confidence": 0-100, "reasoning": str}

AGENT_REGISTRY 提供完整的 key→function 映射。
"""

from __future__ import annotations

import json
import math
import statistics
from typing import Any

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _try_float(x: Any) -> float | None:
    if x is None or x == "" or x == "-": return None
    try: return float(str(x).replace(",", ""))
    except: return None

def _signal(score: float, max_score: float, bullish_thr: float = 0.6, bearish_thr: float = 0.33) -> tuple[str, int]:
    """根据得分比例返回 signal + confidence."""
    if max_score <= 0: return "neutral", 0
    ratio = score / max_score
    if ratio >= bullish_thr: return "bullish", round(min(ratio * 100, 95))
    if ratio <= bearish_thr: return "bearish", round(min((1 - ratio) * 100, 95))
    return "neutral", round(50 - abs(ratio - 0.5) * 100)

def _cagr(seq: list[float]) -> float | None:
    seq = [s for s in seq if s is not None and s > 0]
    if len(seq) < 2: return None
    return (seq[0] / seq[-1]) ** (1 / (len(seq) - 1)) - 1

def _corr(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b)); a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da > 0 and db > 0 else 0

def _safe(m: dict | None) -> dict | None: return m[0] if m else None

# ---------------------------------------------------------------------------
# 1. Warren Buffett
# ---------------------------------------------------------------------------

def warren_buffett_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not metrics: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    score, details = 0, {}
    m = metrics
    # fundamentals (max 10)
    f = 0
    if m.get("return_on_equity") and m["return_on_equity"] > 0.15: f += 2
    if m.get("debt_to_equity") and m["debt_to_equity"] < 0.5: f += 2
    if m.get("operating_margin") and m["operating_margin"] > 0.15: f += 2
    if m.get("current_ratio") and m["current_ratio"] > 1.5: f += 1
    if m.get("gross_margin") and m["gross_margin"] > 0.5: f += 1
    if m.get("return_on_assets") and m["return_on_assets"] > 0.1: f += 2
    details["fundamentals"] = f; score += f
    # consistency (max 3)
    if line_items and len(line_items) >= 2:
        eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]
        eps_seq = [e for e in eps_seq if e is not None]
        if len(eps_seq) >= 2 and all(eps_seq[i] >= eps_seq[i+1] * 0.9 for i in range(len(eps_seq)-1)):
            score += 3; details["consistency"] = 3
    # moat (max 5)
    moat = 0
    if m.get("return_on_equity") and m["return_on_equity"] > 0.15: moat += 2
    if m.get("gross_margin") and m["gross_margin"] > 0.4: moat += 2
    if m.get("return_on_assets") and m["return_on_assets"] > 0.1: moat += 1
    details["moat"] = moat; score += moat
    score += 1; details["management"] = 1
    # intrinsic DCF
    iv = 0
    if line_items and line_items[0].get("free_cash_flow"):
        fcf0 = _try_float(line_items[0]["free_cash_flow"]) or 0
        g = min(max(m.get("revenue_growth") or 0.05, 0), 0.08)
        pv = sum(fcf0 * (1+g)**y / 1.1**y for y in range(1, 6))
        term = fcf0 * (1+g)**5 * 1.025 / 0.075
        iv = (pv + term / 1.1**5) * 0.85; details["intrinsic_value"] = round(iv, 2)
    bvg = m.get("book_value_growth")
    if bvg is not None:
        score += 3 if bvg > 0.10 else (2 if bvg > 0.05 else (1 if bvg > 0 else 0))
    pp = 0; gm = m.get("gross_margin")
    if gm is not None:
        pp += 2 if gm > 0.5 else (1 if gm > 0.3 else 0)
    score += pp; details["pricing_power"] = pp
    mos = 0
    if market_cap and m.get("total_shares") and iv:
        cp = market_cap / m["total_shares"]; mos = (iv - cp) / cp if cp else 0
        details["margin_of_safety"] = round(mos, 4)
    details["total_score"] = score; details["max_score"] = 27
    sig, conf = ("bullish", min(70+score, 95)) if (score>=18 and mos>0) else \
                (("bearish", min(60+(27-score), 95)) if (score<=9 or mos<-0.4) else ("neutral", 50))
    return {"signal": sig, "confidence": conf, "reasoning": json.dumps(details, ensure_ascii=False)[:200]}

# ---------------------------------------------------------------------------
# 2. Ben Graham
# ---------------------------------------------------------------------------

def ben_graham_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not line_items: return {"signal":"neutral","confidence":0,"reasoning":"no line items"}
    score, details = 0, []
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]
    eps_seq = [e for e in eps_seq if e is not None]
    if len(eps_seq) >= 2:
        positive = sum(1 for e in eps_seq if e > 0)
        if positive == len(eps_seq): score += 3; details.append("EPS all positive")
        elif positive >= len(eps_seq) * 0.8: score += 2
        if eps_seq[0] > eps_seq[-1]: score += 1; details.append("EPS growing")
    li0 = line_items[0]
    ca, cl = _try_float(li0.get("current_assets")), _try_float(li0.get("current_liabilities"))
    ta, tl = _try_float(li0.get("total_assets")), _try_float(li0.get("total_liabilities"))
    if ca and cl and cl > 0:
        cr = ca / cl; score += 2 if cr >= 2 else (1 if cr >= 1.5 else 0)
    if ta and tl and ta > 0:
        dr = tl / ta; score += 2 if dr < 0.5 else (1 if dr < 0.8 else 0)
    score += 1
    eps, bvps = _try_float(li0.get("earnings_per_share")) or 0, _try_float(li0.get("book_value_per_share")) or 0
    ncav = (ca or 0) - (tl or 0)
    if ncav > 0 and market_cap and market_cap > 0:
        if ncav > market_cap: score += 4; details.append("NCAV > mcap")
        elif ncav / market_cap >= 0.67: score += 2
    if eps > 0 and bvps > 0:
        gn = math.sqrt(22.5 * eps * bvps)
        shares = _try_float(li0.get("outstanding_shares"))
        if shares and shares > 0:
            price = market_cap / shares
            if price > 0:
                mos = (gn - price) / price
                if mos > 0.5: score += 3
                elif mos > 0.2: score += 1
    sig, conf = _signal(score, 15, bullish_thr=0.7, bearish_thr=0.3)
    return {"signal": sig, "confidence": conf, "reasoning": f"score {score}/15 {'; '.join(details[:3])}"[:200]}

# ---------------------------------------------------------------------------
# 3. Peter Lynch
# ---------------------------------------------------------------------------

def peter_lynch_agent(ticker, metrics, line_items, market_cap, prices=None, news=None, **kwargs) -> dict:
    if not line_items: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    scores = {}
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]; rev_seq = [v for v in rev_seq if v is not None]
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]; eps_seq = [v for v in eps_seq if v is not None]
    raw = 0
    if len(rev_seq) >= 2 and rev_seq[-1] > 0:
        rg = (rev_seq[0] - rev_seq[-1]) / abs(rev_seq[-1])
        raw += 3 if rg > 0.25 else (2 if rg > 0.10 else (1 if rg > 0.02 else 0))
    if len(eps_seq) >= 2 and abs(eps_seq[-1]) > 1e-9:
        eg = (eps_seq[0] - eps_seq[-1]) / abs(eps_seq[-1])
        raw += 3 if eg > 0.25 else (2 if eg > 0.10 else (1 if eg > 0.02 else 0))
    scores["growth"] = min((raw / 6) * 10, 10)
    raw = 0; m = metrics or {}
    eps0 = _try_float(line_items[0].get("earnings_per_share"))
    if eps0 and eps0 > 0 and market_cap and len(line_items) > 1:
        ni0 = _try_float(line_items[0].get("net_income")) or 0
        if ni0 > 0:
            pe = market_cap / ni0; raw += 2 if pe < 15 else (1 if pe < 25 else 0)
    if len(eps_seq) >= 2 and eps_seq[-1] > 0 and eps_seq[0] > 0:
        cagr_v = (eps_seq[0] / eps_seq[-1]) ** (1 / (len(eps_seq) - 1)) - 1
        if market_cap and (_try_float(line_items[0].get("net_income")) or 1):
            pe = market_cap / (_try_float(line_items[0].get("net_income")) or 1)
            if cagr_v > 0: peg = pe / (cagr_v * 100); raw += 3 if peg < 1 else (2 if peg < 2 else (1 if peg < 3 else 0))
    scores["valuation"] = min((raw / 5) * 10, 10)
    raw = 0
    if m.get("debt_to_equity") is not None: raw += 2 if m["debt_to_equity"] < 0.5 else (1 if m["debt_to_equity"] < 1.0 else 0)
    if m.get("operating_margin") is not None: raw += 2 if m["operating_margin"] > 0.20 else (1 if m["operating_margin"] > 0.10 else 0)
    if m.get("free_cash_flow_per_share") and m["free_cash_flow_per_share"] > 0: raw += 2
    scores["fundamentals"] = min((raw / 6) * 10, 10)
    if news: neg = sum(1 for n in news if n.get("sentiment") == "bearish"); scores["sentiment"] = 3 if neg/len(news) > 0.3 else (6 if neg > 0 else 8)
    else: scores["sentiment"] = 5
    scores["insider"] = 5
    total = scores["growth"]*0.30 + scores["valuation"]*0.25 + scores["fundamentals"]*0.20 + scores["sentiment"]*0.15 + scores["insider"]*0.10
    if total >= 7.5: return {"signal":"bullish","confidence":min(round(total*10),90),"reasoning":f"total {total:.1f}/10 PEG focus"[:200]}
    if total <= 4.5: return {"signal":"bearish","confidence":min(round((10-total)*10),90),"reasoning":f"total {total:.1f}/10"[:200]}
    return {"signal":"neutral","confidence":50,"reasoning":f"total {total:.1f}/10"}

# ---------------------------------------------------------------------------
# 4. Nassim Taleb
# ---------------------------------------------------------------------------

def nassim_taleb_agent(ticker, metrics, line_items, market_cap, prices=None, **kwargs) -> dict:
    score, m = 0, metrics or {}
    if prices and len(prices) >= 30:
        rets = [prices[i]["close"] / prices[i-1]["close"] - 1 for i in range(1, len(prices)) if prices[i-1]["close"]]
        if rets:
            tail5 = sorted(rets)[:max(1, len(rets)//20)]
            tr = abs(sum(tail5)/len(tail5)) if tail5 else 0; score += 3 if tr < 0.03 else (1 if tr < 0.05 else 0)
            peak = max(prices, key=lambda p: p["close"])["close"]
            trough = min(prices, key=lambda p: p["close"])["close"]
            dd = (peak - trough) / peak if peak > 0 else 0; score += 2 if dd < 0.3 else 0
    if m.get("current_ratio") and m["current_ratio"] > 1.5: score += 2
    if m.get("debt_to_equity") is not None and m["debt_to_equity"] < 0.3: score += 2
    if m.get("operating_margin") and m["operating_margin"] > 0.15: score += 2
    if m.get("free_cash_flow_per_share") and m["free_cash_flow_per_share"] > 0: score += 2
    if m.get("revenue_growth") and m["revenue_growth"] > 0.20: score += 3
    if m.get("gross_margin") and m["gross_margin"] > 0.5: score += 2
    if m.get("debt_to_equity") and m["debt_to_equity"] > 1: score -= 3
    if m.get("operating_margin") is not None and m["operating_margin"] < 0.05: score -= 1
    score += 3  # placeholder skin_in_game + vol + sentinel
    if score >= 35: return {"signal":"bullish","confidence":min(70+score-35,95),"reasoning":f"antifragile {score}/50"[:200]}
    if score <= 20: return {"signal":"bearish","confidence":min(70+20-score,95),"reasoning":f"fragile {score}/50"[:200]}
    return {"signal":"neutral","confidence":50,"reasoning":f"score {score}/50"}

# ---------------------------------------------------------------------------
# 5. Aswath Damodaran（完整独立算法，移植自原项目 aswath_damodaran.py）
# ---------------------------------------------------------------------------

def aswath_damodaran_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not metrics or not line_items or not market_cap: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    m, score, details = metrics, 0, []
    rev_growth = m.get("revenue_growth")
    gs = 0
    if rev_growth is not None:
        gs += 2 if rev_growth > 0.08 else (1 if rev_growth > 0.03 else 0); details.append(f"rev CAGR {rev_growth:.1%}" if rev_growth > 0.03 else "")
    fcf_seq = [_try_float(li.get("free_cash_flow")) for li in (line_items or [])]; fcf_seq = [f for f in fcf_seq if f is not None]
    if len(fcf_seq) >= 2 and fcf_seq[0] > fcf_seq[-1]: gs += 1; details.append("FCFF growing")
    roic = m.get("return_on_invested_capital")
    if roic is not None and roic > 0.10: gs += 1; details.append(f"ROIC {roic:.1%}")
    score += gs
    rs = 0; de = m.get("debt_to_equity")
    if de is not None and de < 1.0: rs += 1; details.append(f"D/E {de:.2f}")
    op_mg = m.get("operating_margin")
    if op_mg is not None and op_mg > 0.15: rs += 1; details.append("op margin safe")
    score += rs
    pe = m.get("price_to_earnings_ratio")
    if pe is not None and pe < 18: score += 1; details.append(f"PE cheap {pe:.1f}")
    dcf_ps = 0; eps = _try_float(line_items[0].get("earnings_per_share")) if line_items else None
    if eps and eps > 0:
        discount, g, tg = 0.09, min(rev_growth or 0.04, 0.10), 0.025
        pv = sum(eps * (1+min(g+(tg-g)/(9)*(yr-1), tg)) / (1+discount)**yr for yr in range(1, 11))
        tv = eps * (1+tg) / (discount - tg) / (1+discount)**10; dcf_ps = pv + tv
    sig, conf = _signal(score, 8, bullish_thr=0.6, bearish_thr=0.3)
    return {"signal": sig, "confidence": conf, "reasoning": f"Damodaran on {ticker}: {score}/8 DCF≈{dcf_ps:.0f}/sh {'; '.join(details[:4])}"[:200]}

# ---------------------------------------------------------------------------
# 6. Bill Ackman（移植自 bill_ackman.py）
# ---------------------------------------------------------------------------

def bill_ackman_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not line_items or not market_cap: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    score = 0; details = []
    # business quality (max 5)
    revs = [_try_float(li.get("revenue")) for li in line_items]; revs = [r for r in revs if r is not None]
    if len(revs) >= 2 and revs[0] > 0:
        rg = (revs[0] - revs[-1]) / abs(revs[-1]); score += 2 if rg > 0.5 else (1 if rg > 0 else 0)
        details.append(f"rev growth {rg:.1%}")
    oms = [_try_float(li.get("operating_income")) and _try_float(li.get("revenue")) and _try_float(li.get("operating_income")) / (_try_float(li.get("revenue")) or 1) for li in line_items]
    oms = [o for o in oms if o is not None]; n = len(oms)
    if n > 0 and sum(1 for o in oms if o > 0.15) >= (n+1)//2: score += 2; details.append("op margin strong")
    fcf_vals = [_try_float(li.get("free_cash_flow")) for li in line_items]; fcf_vals = [f for f in fcf_vals if f is not None]
    if len(fcf_vals) > 0 and sum(1 for f in fcf_vals if f > 0) >= (len(fcf_vals)+1)//2: score += 1; details.append("FCF positive")
    # financial discipline (max 4)
    de_vals = [_try_float(li.get("debt_to_equity")) for li in line_items]; de_vals = [d for d in de_vals if d is not None]
    if len(de_vals) > 0 and sum(1 for d in de_vals if d < 1.0) >= (len(de_vals)+1)//2: score += 2; details.append("D/E disciplined")
    div_vals = [_try_float(li.get("dividends_and_other_cash_distributions")) for li in line_items]; div_vals = [d for d in div_vals if d is not None]
    if len(div_vals) > 0 and sum(1 for d in div_vals if d < 0) >= (len(div_vals)+1)//2: score += 1; details.append("pays dividends")
    shares = [_try_float(li.get("outstanding_shares")) for li in line_items]; shares = [s for s in shares if s is not None]
    if len(shares) >= 2 and shares[0] < shares[-1]: score += 1; details.append("buyback")
    # activism (max 2)
    if revs and len(revs) >= 2 and revs[-1] > 0:
        ra = (revs[0] - revs[-1]) / abs(revs[-1])
        if ra > 0.15 and oms and sum(oms)/len(oms) < 0.10: score += 2; details.append("activism opportunity")
    # valuation (max 3): simplified DCF
    fcf = _try_float(line_items[0].get("free_cash_flow"))
    if fcf and fcf > 0 and market_cap:
        iv = sum(fcf * 1.06**y / 1.10**y for y in range(1, 6)) + (fcf * 1.06**5 * 15 / 1.10**5)
        mos = (iv - market_cap) / market_cap
        score += 3 if mos > 0.3 else (1 if mos > 0.1 else 0); details.append(f"MoS {mos:.1%}")
    sig, conf = _signal(score, 14, bullish_thr=0.7, bearish_thr=0.3)
    return {"signal": sig, "confidence": conf, "reasoning": f"Ackman on {ticker}: {score}/14 {'; '.join(details[:4])}"[:200]}

# ---------------------------------------------------------------------------
# 7. Cathie Wood（移植自 cathie_wood.py）
# ---------------------------------------------------------------------------

def cathie_wood_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not line_items: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    m = metrics or {}
    # disruptive potential (raw 0-12, scaled to 0-5)
    dps = 0; ddet = []
    revs = [_try_float(li.get("revenue")) for li in line_items]; revs = [r for r in revs if r is not None]
    if len(revs) >= 2 and revs[-1] > 0:
        rates = [(revs[i] - revs[i+1]) / abs(revs[i+1]) for i in range(len(revs)-1)]
        rates = [r for r in rates if r is not None]
        if rates and rates[0] > rates[-1]: dps += 2; ddet.append("rev accelerating")
        latest = rates[0] if rates else 0
        dps += 3 if latest > 1.0 else (2 if latest > 0.5 else (1 if latest > 0.2 else 0))
    gms = [_try_float(li.get("gross_margin")) for li in line_items]; gms = [g for g in gms if g is not None]
    if len(gms) >= 2:
        trend = gms[0] - gms[-1]; dps += 2 if trend > 0.05 else (1 if trend > 0 else 0)
    if gms and gms[0] > 0.5: dps += 2
    dsc = min((dps / 12) * 5, 5)
    # innovation growth (raw 0-15, scaled to 0-5)
    igs = 0
    rd_seq = [_try_float(li.get("research_and_development")) for li in line_items]; rd_seq = [r for r in rd_seq if r is not None]
    if len(rd_seq) >= 2:
        rd_g = (rd_seq[0] - rd_seq[-1]) / abs(rd_seq[-1]) if rd_seq[-1] else 0
        igs += 3 if rd_g > 0.5 else (2 if rd_g > 0.2 else 0)
    fcf_vals = [_try_float(li.get("free_cash_flow")) for li in line_items]; fcf_vals = [f for f in fcf_vals if f is not None]
    if len(fcf_vals) >= 2 and fcf_vals[-1] > 0:
        fg = (fcf_vals[0] - fcf_vals[-1]) / abs(fcf_vals[-1])
        igs += 3 if fg > 0.3 and all(f > 0 for f in fcf_vals) else (2 if sum(1 for f in fcf_vals if f > 0)/len(fcf_vals) >= 0.75 else 0)
    op_mgs = [_try_float(li.get("operating_margin")) for li in line_items]; op_mgs = [o for o in op_mgs if o is not None]
    if op_mgs and op_mgs[0] is not None:
        igs += 3 if op_mgs[0] > 0.15 else (2 if op_mgs[0] > 0.10 else 0)
    isc = min((igs / 15) * 5, 5)
    # valuation (max 3)
    vs = 0; fcf = _try_float(line_items[0].get("free_cash_flow"))
    if fcf and fcf > 0 and market_cap:
        iv = sum(fcf * 1.20**y / 1.15**y for y in range(1, 6)) + (fcf * 1.20**5 * 25 / 1.15**5)
        mos = (iv - market_cap) / market_cap; vs = 3 if mos > 0.5 else (1 if mos > 0.2 else 0)
    total = dsc + isc + vs; sig, conf = _signal(total, 13, 0.7, 0.3)
    return {"signal": sig, "confidence": conf, "reasoning": f"Wood on {ticker}: {total:.1f}/13 (disrupt {dsc:.1f} innov {isc:.1f} val {vs})"[:200]}

# ---------------------------------------------------------------------------
# 8. Charlie Munger（移植自 charlie_munger.py — 最复杂的算法之一）
# ---------------------------------------------------------------------------

def charlie_munger_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not line_items: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    m = metrics or {}
    # moat (0-9 raw → 0-10)
    moat_raw = 0
    roics = [_try_float(li.get("return_on_invested_capital")) for li in line_items]; roics = [r for r in roics if r is not None]
    if roics:
        above = sum(1 for r in roics if r > 0.15) / len(roics)
        moat_raw += 3 if above >= 0.8 else (2 if above >= 0.5 else (1 if above > 0 else 0))
    gms = [_try_float(li.get("gross_margin")) for li in line_items]; gms = [g for g in gms if g is not None]
    if len(gms) >= 2:
        improving = sum(1 for i in range(len(gms)-1) if gms[i] > gms[i+1]) / (len(gms)-1)
        moat_raw += 2 if improving >= 0.7 else 0
    avg_gm = sum(gms)/len(gms) if gms else 0; moat_raw += 1 if avg_gm > 0.3 else 0
    capex_seq = [_try_float(li.get("capital_expenditure")) for li in line_items]; capex_seq = [c for c in capex_seq if c is not None]
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]; rev_seq = [r for r in rev_seq if r is not None]
    if capex_seq and rev_seq and len(capex_seq) == len(rev_seq):
        avg_ratio = sum(c/r for c, r in zip(capex_seq, rev_seq) if r and r > 0) / len(capex_seq)
        moat_raw += 2 if avg_ratio < 0.05 else (1 if avg_ratio < 0.10 else 0)
    moat = min((moat_raw / 9) * 10, 10)
    # management (0-12 raw → 0-10)
    mgmt_raw = 0
    ni_seq = [_try_float(li.get("net_income")) for li in line_items]; ni_seq = [n for n in ni_seq if n is not None]
    fcf_seq = [_try_float(li.get("free_cash_flow")) for li in line_items]; fcf_seq = [f for f in fcf_seq if f is not None]
    if ni_seq and fcf_seq and len(ni_seq) >= 3 and len(fcf_seq) >= 3 and ni_seq[-1] > 0:
        ratios = [f/n for f, n in zip(fcf_seq[:3], ni_seq[:3]) if n > 0]
        avg = sum(ratios)/len(ratios) if ratios else 0
        mgmt_raw += 3 if avg > 1.1 else (2 if avg > 0.9 else (1 if avg > 0.7 else 0))
    de_vals = [_try_float(li.get("debt_to_equity")) for li in line_items]; de_vals = [d for d in de_vals if d is not None]
    if de_vals: de = de_vals[0]; mgmt_raw += 3 if de < 0.3 else (2 if de < 0.7 else (1 if de < 1.5 else 0))
    mgmt = max(0, min((mgmt_raw / 12) * 10, 10))
    # predictability (0-10 raw → 0-10)
    pred_raw = 0
    if len(rev_seq) >= 5:
        rates = [(rev_seq[i]-rev_seq[i+1])/abs(rev_seq[i+1]) for i in range(len(rev_seq)-1) if rev_seq[i+1] and rev_seq[i+1] > 0]
        avg_rate = sum(rates)/len(rates) if rates else 0
        vol = statistics.stdev(rates) if len(rates) > 1 else 1
        pred_raw += 3 if avg_rate > 0.05 and vol < 0.1 else (2 if avg_rate > 0 and vol < 0.2 else (1 if avg_rate > 0 else 0))
    ops = [_try_float(li.get("operating_income")) for li in line_items]; ops = [o for o in ops if o is not None]
    if ops: pred_raw += 3 if all(o > 0 for o in ops) else (2 if sum(1 for o in ops if o > 0)/len(ops) >= 0.8 else 0)
    pred = min((pred_raw / 10) * 10, 10)
    # valuation (0-10 raw → 0-10)
    val_raw = 0; fcf = _try_float(line_items[0].get("free_cash_flow"))
    if fcf and fcf > 0 and market_cap:
        fy = fcf / market_cap; val_raw += 4 if fy > 0.08 else (3 if fy > 0.05 else (1 if fy > 0.03 else 0))
        if len(fcf_seq) >= 6:
            recent = sum(fcf_seq[:3])/3; older = sum(fcf_seq[3:6])/3
            val_raw += 3 if recent > older * 1.2 else (2 if recent > older else 0)
    val = min((val_raw / 10) * 10, 10)
    # weighted total (35/25/25/15)
    total = moat * 0.35 + mgmt * 0.25 + pred * 0.25 + val * 0.15
    sig, conf = _signal(total, 10, 0.75, 0.55)
    return {"signal": sig, "confidence": conf, "reasoning": f"Munger on {ticker}: {total:.1f}/10 (moat {moat:.1f} mgmt {mgmt:.1f} pred {pred:.1f})"[:200]}

# ---------------------------------------------------------------------------
# 9. Michael Burry（移植自 michael_burry.py）
# ---------------------------------------------------------------------------

def michael_burry_agent(ticker, metrics, line_items, market_cap, prices=None, news=None, **kwargs) -> dict:
    if not line_items or not market_cap: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    score = 0; details = []
    # value (max 6)
    fcf = _try_float(line_items[0].get("free_cash_flow"))
    if fcf and fcf > 0:
        fy = fcf / market_cap; score += 4 if fy >= 0.15 else (3 if fy >= 0.12 else (2 if fy >= 0.08 else 0))
        details.append(f"FCF yield {fy:.1%}")
    ebit = _try_float(line_items[0].get("ebit"))
    if ebit and ebit > 0:
        ev_ebit = market_cap / ebit; score += 2 if ev_ebit < 6 else (1 if ev_ebit < 10 else 0)
    # balance sheet (max 3)
    de = _try_float(line_items[0].get("debt_to_equity")); cd = _try_float(line_items[0].get("cash_and_equivalents")); td = _try_float(line_items[0].get("total_debt"))
    if de is not None: score += 2 if de < 0.5 else (1 if de < 1.0 else 0)
    if cd and td and cd > td: score += 1; details.append("net cash")
    # insider (max 2) — placeholder, no insider data in script mode
    score += 1
    # contrarian (max 1) — placeholder
    score += 1
    sig, conf = _signal(score, 12, 0.7, 0.3)
    return {"signal": sig, "confidence": conf, "reasoning": f"Burry on {ticker}: {score}/12 {'; '.join(details)}"[:200]}

# ---------------------------------------------------------------------------
# 10. Mohnish Pabrai（移植自 mohnish_pabrai.py）
# ---------------------------------------------------------------------------

def mohnish_pabrai_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not line_items or not market_cap: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    # downside (max 10)
    ds = 0
    cd = _try_float(line_items[0].get("cash_and_equivalents")); td = _try_float(line_items[0].get("total_debt"))
    if cd and td: ds += 3 if cd - td > 0 else 0
    ca = _try_float(line_items[0].get("current_assets")); cl = _try_float(line_items[0].get("current_liabilities"))
    if ca and cl and cl > 0: cr = ca / cl; ds += 2 if cr >= 2 else (1 if cr >= 1.2 else 0)
    de = _try_float(line_items[0].get("debt_to_equity")); ds += 2 if de is not None and de < 0.3 else (1 if de is not None and de < 0.7 else 0)
    fcf_seq = [_try_float(li.get("free_cash_flow")) for li in line_items]; fcf_seq = [f for f in fcf_seq if f is not None]
    if len(fcf_seq) >= 3:
        recent = sum(fcf_seq[:3])/3; older = fcf_seq[-1]; ds += 2 if recent > 0 and recent >= older else (1 if recent > 0 else 0)
    ds = min(ds, 10)
    # valuation (max 10)
    vs = 0
    if fcf_seq and len(fcf_seq) <= 5:
        nfcf = sum(fcf_seq) / len(fcf_seq); fy = nfcf / market_cap if nfcf > 0 else 0
        vs += 4 if fy > 0.10 else (3 if fy > 0.07 else (2 if fy > 0.05 else (1 if fy > 0.03 else 0)))
    capex_seq = [_try_float(li.get("capital_expenditure")) for li in line_items]; capex_seq = [c for c in capex_seq if c is not None]
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]; rev_seq = [r for r in rev_seq if r is not None]
    if capex_seq and rev_seq and len(capex_seq)>0 and len(rev_seq)>0 and sum(capex_seq)/sum(rev_seq) and sum(rev_seq)>0:
        vs += 2 if sum(capex_seq)/sum(rev_seq) < 0.05 else (1 if sum(capex_seq)/sum(rev_seq) < 0.10 else 0)
    vs = min(vs, 10)
    # double potential (max 10)
    dp = 0
    if len(rev_seq) >= 3:
        rg = (sum(rev_seq[:3])/3 - rev_seq[-1]) / abs(rev_seq[-1]) if rev_seq[-1] else 0
        dp += 2 if rg > 0.15 else (1 if rg > 0.05 else 0)
    if len(fcf_seq) >= 3:
        fg = (sum(fcf_seq[:3])/3 - fcf_seq[-1]) / abs(fcf_seq[-1]) if fcf_seq[-1] else 0
        dp += 3 if fg > 0.20 else (2 if fg > 0.08 else (1 if fg > 0 else 0))
    if nfcf and nfcf > 0: fy = nfcf / market_cap; dp += 3 if fy > 0.08 else (1 if fy > 0.05 else 0)
    dp = min(dp, 10)
    total = ds * 0.45 + vs * 0.35 + dp * 0.20
    sig, conf = _signal(total, 10, 0.75, 0.4)
    return {"signal": sig, "confidence": conf, "reasoning": f"Pabrai on {ticker}: {total:.1f}/10 (downside {ds:.0f} val {vs:.0f} double {dp:.0f})"[:200]}

# ---------------------------------------------------------------------------
# 11. Phil Fisher（移植自 phil_fisher.py）
# ---------------------------------------------------------------------------

def phil_fisher_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not line_items: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]; rev_seq = [r for r in rev_seq if r is not None]
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]; eps_seq = [e for e in eps_seq if e is not None]
    # growth quality (0-9 raw → 0-10)
    gq_raw = 0
    if len(rev_seq) >= 2 and rev_seq[-1] > 0:
        rc = (rev_seq[0] / rev_seq[-1]) ** (1/(len(rev_seq)-1)) - 1
        gq_raw += 3 if rc > 0.20 else (2 if rc > 0.10 else (1 if rc > 0.03 else 0))
    if len(eps_seq) >= 2 and eps_seq[-1] > 0:
        ec = (eps_seq[0] / eps_seq[-1]) ** (1/(len(eps_seq)-1)) - 1
        gq_raw += 3 if ec > 0.20 else (2 if ec > 0.10 else (1 if ec > 0.03 else 0))
    rd = _try_float(line_items[0].get("research_and_development")); rv = _try_float(line_items[0].get("revenue"))
    if rd and rv and rv > 0:
        ri = rd / rv; gq_raw += 3 if 0.03 <= ri <= 0.15 else (2 if ri > 0.15 else (1 if ri > 0 else 0))
    gq = min((gq_raw / 9) * 10, 10)
    # margins (0-6 raw → 0-10)
    mg_raw = 0
    oms = [_try_float(li.get("operating_margin")) for li in line_items]; oms = [o for o in oms if o is not None]
    if len(oms) >= 2: mg_raw += 2 if oms[0] >= oms[-1] > 0 else (1 if oms[0] > 0 else 0)
    gm = _try_float(line_items[0].get("gross_margin")); mg_raw += 2 if gm and gm > 0.50 else (1 if gm and gm > 0.30 else 0)
    if len(oms) >= 3: sv = statistics.stdev(oms); mg_raw += 2 if sv < 0.02 else (1 if sv < 0.05 else 0)
    mg = min((mg_raw / 6) * 10, 10)
    # mgmt efficiency (0-6 raw → 0-10)
    me_raw = 0
    ni = _try_float(line_items[0].get("net_income")); eq = _try_float(line_items[0].get("shareholders_equity"))
    if ni and eq and eq > 0: roe = ni / eq; me_raw += 3 if roe > 0.20 else (2 if roe > 0.10 else (1 if roe > 0 else 0))
    de = _try_float(line_items[0].get("debt_to_equity")); me_raw += 2 if de is not None and de < 0.3 else (1 if de is not None and de < 1.0 else 0)
    fcf_seq = [_try_float(li.get("free_cash_flow")) for li in line_items]; fcf_seq = [f for f in fcf_seq if f is not None]
    if fcf_seq: me_raw += 1 if sum(1 for f in fcf_seq if f > 0) / len(fcf_seq) > 0.8 else 0
    me = min((me_raw / 6) * 10, 10)
    # valuation (0-4 raw → 0-10)
    val_raw = 0; ni0 = _try_float(line_items[0].get("net_income")); fcf0 = _try_float(line_items[0].get("free_cash_flow"))
    if ni0 and ni0 > 0: pe = market_cap / ni0; val_raw += 2 if pe < 20 else (1 if pe < 30 else 0)
    if fcf0 and fcf0 > 0: pfcf = market_cap / fcf0; val_raw += 2 if pfcf < 20 else (1 if pfcf < 30 else 0)
    val = min((val_raw / 4) * 10, 10)
    # insider (0-10, default 5)
    insider = 5
    # sentiment (0-10, default 5)
    sent = 5
    total = gq*0.30 + mg*0.25 + me*0.20 + val*0.15 + insider*0.05 + sent*0.05
    sig, conf = _signal(total, 10, 0.75, 0.45)
    return {"signal": sig, "confidence": conf, "reasoning": f"Fisher on {ticker}: {total:.1f}/10 (grow {gq:.1f} marg {mg:.1f} eff {me:.1f})"[:200]}

# ---------------------------------------------------------------------------
# 12. Rakesh Jhunjhunwala（移植自 rakesh_jhunjhunwala.py）
# ---------------------------------------------------------------------------

def rakesh_jhunjhunwala_agent(ticker, metrics, line_items, market_cap, **kwargs) -> dict:
    if not line_items or not market_cap: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    score = 0; ni = _try_float(line_items[0].get("net_income")); eq = _try_float(line_items[0].get("shareholders_equity"))
    # profitability (max 8)
    pf = 0
    if ni and eq and eq > 0: roe = ni / eq; pf += 3 if roe > 0.20 else (2 if roe > 0.15 else (1 if roe > 0.10 else 0))
    op = _try_float(line_items[0].get("operating_income")); rv = _try_float(line_items[0].get("revenue"))
    if op and rv and rv > 0: om = op / rv; pf += 2 if om > 0.20 else (1 if om > 0.15 else 0)
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]; eps_seq = [e for e in eps_seq if e is not None]
    if len(eps_seq) >= 3 and eps_seq[-1] > 0:
        ec = (eps_seq[0] / eps_seq[-1]) ** (1/(len(eps_seq)-1)) - 1
        pf += 3 if ec > 0.20 else (2 if ec > 0.15 else (1 if ec > 0.10 else 0))
    score += pf
    # growth (max 7)
    gs = 0
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]; rev_seq = [r for r in rev_seq if r is not None]
    if len(rev_seq) >= 3 and rev_seq[-1] > 0:
        rc = (rev_seq[0] / rev_seq[-1]) ** (1/(len(rev_seq)-1)) - 1
        gs += 3 if rc > 0.20 else (2 if rc > 0.15 else (1 if rc > 0.10 else 0))
    if ni and eq and eq > 0 and len(eps_seq) >= 3 and eps_seq[-1] > 0:
        nc = (eps_seq[0] / eps_seq[-1]) ** (1/(len(eps_seq)-1)) - 1
        gs += 3 if nc > 0.25 else (2 if nc > 0.20 else (1 if nc > 0.15 else 0))
    score += gs
    # balance sheet (max 4)
    ta = _try_float(line_items[0].get("total_assets")); tl = _try_float(line_items[0].get("total_liabilities"))
    if ta and tl and ta > 0: dr = tl / ta; score += 2 if dr < 0.5 else (1 if dr < 0.7 else 0)
    ca = _try_float(line_items[0].get("current_assets")); cl = _try_float(line_items[0].get("current_liabilities"))
    if ca and cl and cl > 0: cr = ca / cl; score += 2 if cr > 2.0 else (1 if cr > 1.5 else 0)
    # cash flow (max 3)
    fcf = _try_float(line_items[0].get("free_cash_flow")); score += 2 if fcf and fcf > 0 else 0
    score += 1
    # management (max 2): skip issuance check, default +1
    score += 1
    # simplified intrinsic value
    iv = 0; fcf0 = _try_float(line_items[0].get("free_cash_flow"))
    if fcf0 and fcf0 > 0:
        sg = min(0.20, max((rev_seq[0]/rev_seq[-1])**(1/(len(rev_seq)-1))-1 if len(rev_seq)>=3 and rev_seq[-1]>0 else 0.05, 0.05))
        iv = sum(fcf0 * (1+sg)**y / 1.15**y for y in range(1, 6)) + fcf0 * (1+sg)**5 * 15 / 1.15**5
    mos = (iv - market_cap) / market_cap if iv and market_cap else 0
    if mos >= 0.3: sig, conf = "bullish", min(max(abs(mos)*150, 20), 95)
    elif mos <= -0.3: sig, conf = "bearish", min(max(abs(mos)*150, 20), 95)
    else: sig, conf = _signal(score, 24, 0.6, 0.3)
    return {"signal": sig, "confidence": conf, "reasoning": f"Jhunjhunwala on {ticker}: {score}/24 MoS {mos:.1%}"[:200]}

# ---------------------------------------------------------------------------
# 13. Stanley Druckenmiller（移植自 stanley_druckenmiller.py）
# ---------------------------------------------------------------------------

def stanley_druckenmiller_agent(ticker, metrics, line_items, market_cap, prices=None, **kwargs) -> dict:
    if not line_items or not market_cap: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]; rev_seq = [r for r in rev_seq if r is not None]
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]; eps_seq = [e for e in eps_seq if e is not None]
    # growth & momentum (0-9 raw → 0-10)
    gm_raw = 0
    if len(rev_seq) >= 2 and rev_seq[-1] > 0:
        rc = (rev_seq[0] / rev_seq[-1]) ** (1/(len(rev_seq)-1)) - 1
        gm_raw += 3 if rc > 0.08 else (2 if rc > 0.04 else (1 if rc > 0.01 else 0))
    if len(eps_seq) >= 2 and eps_seq[-1] > 0:
        ec = (eps_seq[0] / eps_seq[-1]) ** (1/(len(eps_seq)-1)) - 1
        gm_raw += 3 if ec > 0.08 else (2 if ec > 0.04 else (1 if ec > 0.01 else 0))
    # price momentum
    if prices and len(prices) >= 30:
        pm = (prices[-1]["close"] - prices[0]["close"]) / prices[0]["close"] if prices[0]["close"] > 0 else 0
        gm_raw += 3 if pm > 0.5 else (2 if pm > 0.2 else (1 if pm > 0 else 0))
    gm = min((gm_raw / 9) * 10, 10)
    # risk/reward (0-6 raw → 0-10)
    rr_raw = 0; de = _try_float(line_items[0].get("debt_to_equity"))
    rr_raw += 3 if de is not None and de < 0.3 else (2 if de is not None and de < 0.7 else (1 if de is not None and de < 1.5 else 0))
    if prices and len(prices) >= 30:
        rets = [prices[i]["close"] / prices[i-1]["close"] - 1 for i in range(1, len(prices)) if prices[i-1]["close"]]
        vs = statistics.stdev(rets) if len(rets) > 1 else 0.02
        rr_raw += 3 if vs < 0.01 else (2 if vs < 0.02 else (1 if vs < 0.04 else 0))
    rr = min((rr_raw / 6) * 10, 10)
    # valuation (0-8 raw → 0-10)
    val_raw = 0; ni0 = _try_float(line_items[0].get("net_income")); fcf0 = _try_float(line_items[0].get("free_cash_flow"))
    pe = market_cap / ni0 if ni0 and ni0 > 0 else 999; val_raw += 2 if pe < 15 else (1 if pe < 25 else 0)
    pfcf = market_cap / fcf0 if fcf0 and fcf0 > 0 else 999; val_raw += 2 if pfcf < 15 else (1 if pfcf < 25 else 0)
    val = min((val_raw / 8) * 10, 10)
    # insider (default 5), sentiment (default 5)
    total = gm*0.35 + rr*0.20 + val*0.20 + 5*0.15 + 5*0.10
    sig, conf = _signal(total, 10, 0.75, 0.45)
    return {"signal": sig, "confidence": conf, "reasoning": f"Druckenmiller on {ticker}: {total:.1f}/10 (growth {gm:.1f} risk {rr:.1f} val {val:.1f})"[:200]}

# ---------------------------------------------------------------------------
# 14-19: 功能型 Agent（保留现有实现）
# ---------------------------------------------------------------------------

def fundamentals_agent(ticker, metrics, line_items=None, market_cap=None, **kwargs) -> dict:
    if not metrics: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    m = metrics; signals = []
    ph = 0
    if m.get("return_on_equity") and m["return_on_equity"] > 0.15: ph += 1
    if m.get("net_margin") and m["net_margin"] > 0.20: ph += 1
    if m.get("operating_margin") and m["operating_margin"] > 0.15: ph += 1
    signals.append("bullish" if ph >= 2 else ("bearish" if ph == 0 else "neutral"))
    gh = 0
    if m.get("revenue_growth") and m["revenue_growth"] > 0.10: gh += 1
    if m.get("earnings_growth") and m["earnings_growth"] > 0.10: gh += 1
    if m.get("book_value_growth") and m["book_value_growth"] > 0.10: gh += 1
    signals.append("bullish" if gh >= 2 else ("bearish" if gh == 0 else "neutral"))
    hh = 0
    if m.get("current_ratio") and m["current_ratio"] > 1.5: hh += 1
    if m.get("debt_to_equity") and m["debt_to_equity"] < 0.5: hh += 1
    if m.get("free_cash_flow_per_share") and m.get("earnings_per_share") and m["free_cash_flow_per_share"] > m["earnings_per_share"] * 0.8: hh += 1
    signals.append("bullish" if hh >= 2 else ("bearish" if hh == 0 else "neutral"))
    pe = m.get("price_to_earnings_ratio"); pb = m.get("price_to_book_ratio")
    oc = sum([pe is not None and pe > 25, pb is not None and pb > 3])
    signals.append("bearish" if oc >= 2 else ("bullish" if oc == 0 else "neutral"))
    bc = signals.count("bullish"); bec = signals.count("bearish")
    if bc > bec: sig, conf = "bullish", round(bc / 4 * 100)
    elif bec > bc: sig, conf = "bearish", round(bec / 4 * 100)
    else: sig, conf = "neutral", 50
    return {"signal": sig, "confidence": conf, "reasoning": f"{bc}B/{bec}Be/{4-bc-bec}N"}

def technicals_agent(ticker, metrics=None, line_items=None, market_cap=None, prices=None, **kwargs) -> dict:
    if not prices or len(prices) < 60: return {"signal":"neutral","confidence":0,"reasoning":f"only {len(prices or [])} days"}
    closes = [p["close"] for p in prices]
    sma20 = sum(closes[-20:]) / 20; sma50 = sum(closes[-50:]) / 50
    trend = ("bullish", 0.7) if closes[-1] > sma20 > sma50 else (("bearish", 0.7) if closes[-1] < sma20 < sma50 else ("neutral", 0.5))
    mom = (closes[-1] - closes[-21]) / closes[-21] if closes[-21] > 0 else 0
    mom_sig = ("bullish", min(abs(mom)*5, 1.0)) if mom > 0.05 else (("bearish", min(abs(mom)*5, 1.0)) if mom < -0.05 else ("neutral", 0.5))
    recent = closes[-20:]; mean = sum(recent)/20; std = statistics.stdev(recent) if len(recent) > 1 else 1
    z = (closes[-1] - mean) / std if std > 0 else 0
    mr = ("bullish", min(abs(z)/3, 1.0)) if z < -1.5 else (("bearish", min(abs(z)/3, 1.0)) if z > 1.5 else ("neutral", 0.5))
    rets = [closes[i] / closes[i-1] - 1 for i in range(1, len(closes))]
    vol = statistics.stdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.25
    weights = {"trend":0.30, "momentum":0.30, "mr":0.20, "vol":0.10, "sa":0.10}
    sc = 0
    for sp, w in [(trend, weights["trend"]), (mom_sig, weights["momentum"]), (mr, weights["mr"])]:
        sc += ({"bullish":1,"neutral":0,"bearish":-1}[sp[0]] * w * sp[1])
    if vol > 0.5: sc -= 0.3
    sig = "bullish" if sc > 0.15 else ("bearish" if sc < -0.15 else "neutral")
    return {"signal": sig, "confidence": min(round(abs(sc)*100), 95), "reasoning": f"trend={trend[0]} mom={mom_sig[0]} mr={mr[0]} vol={vol:.1%}"}

def valuation_agent(ticker, metrics, line_items=None, market_cap=None, **kwargs) -> dict:
    if not metrics or not market_cap: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    m = metrics; pe = m.get("price_to_earnings_ratio"); pb = m.get("price_to_book_ratio")
    pe_sc = 1 if pe and 0 < pe < 15 else (-1 if pe and pe > 30 else 0)
    pb_sc = 1 if pb and 0 < pb < 1.5 else (-1 if pb and pb > 5 else 0)
    eps = _try_float(line_items[0].get("earnings_per_share")) if line_items else None
    dcf_ps = 0
    if eps and eps > 0:
        g = min(max(m.get("revenue_growth") or 0.05, 0), 0.08)
        pv = sum(eps * (1+g)**y / 1.1**y for y in range(1, 6))
        dcf_ps = pv + eps * (1+g)**5 * 1.025 / 0.075 / 1.1**5
    dcf_sc = 1 if dcf_ps > 0 else 0
    score = pe_sc + pb_sc + dcf_sc
    if score >= 2: sig, conf = "bullish", min(60+score*10, 90)
    elif score <= -2: sig, conf = "bearish", min(60-score*10, 90)
    else: sig, conf = "neutral", 50
    return {"signal": sig, "confidence": conf, "reasoning": f"PE={pe:.1f} PB={pb:.1f} DCF_gap={dcf_ps:.1%}"[:200] if pe and pb else "valuation pending"}

def growth_agent(ticker, metrics, line_items=None, market_cap=None, **kwargs) -> dict:
    if not metrics: return {"signal":"neutral","confidence":0,"reasoning":"no data"}
    m = metrics
    rev_seq = [_try_float(li.get("revenue")) for li in (line_items or [])]; rev_seq = [r for r in rev_seq if r is not None]
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in (line_items or [])]; eps_seq = [e for e in eps_seq if e is not None]
    growth_sc = 0
    rev_c = _cagr(rev_seq); eps_c = _cagr(eps_seq)
    for c in [rev_c, eps_c]:
        if c and c > 0.25: growth_sc += 0.25
        elif c and c > 0.15: growth_sc += 0.15
        elif c and c > 0.08: growth_sc += 0.08
    growth_sc = min(growth_sc, 1.0)
    val_sc = 0; pe = m.get("price_to_earnings_ratio")
    if pe and m.get("earnings_growth") and m["earnings_growth"] > 0:
        peg = pe / (m["earnings_growth"] * 100); val_sc += 0.5 if peg < 1 else (0.25 if peg < 2 else 0)
    margin_sc = 0; gm = m.get("gross_margin")
    if gm: margin_sc += 0.2 if gm > 0.5 else 0
    weighted = growth_sc*0.4 + val_sc*0.25 + margin_sc*0.15 + 0.5*0.10 + 0.7*0.10
    if weighted > 0.6: sig, conf = "bullish", round((weighted-0.5)*2*100)
    elif weighted < 0.4: sig, conf = "bearish", round((0.5-weighted)*2*100)
    else: sig, conf = "neutral", 50
    return {"signal": sig, "confidence": min(conf, 95), "reasoning": f"weighted {weighted:.2f}"[:200]}

def news_sentiment_agent(ticker, metrics=None, line_items=None, market_cap=None, news=None, **kwargs) -> dict:
    if not news: return {"signal":"neutral","confidence":0,"reasoning":"no news"}
    b = sum(1 for n in news if n.get("sentiment") == "bullish")
    be = sum(1 for n in news if n.get("sentiment") == "bearish")
    tot = len(news)
    bp, bnp = b/tot, be/tot
    if bp > 0.6: sig, conf = "bullish", round((bp-bnp)*100)
    elif bnp > 0.6: sig, conf = "bearish", round((bnp-bp)*100)
    else: sig, conf = "neutral", round((1-abs(bp-bnp))*50)
    return {"signal": sig, "confidence": conf, "reasoning": f"{b}B/{be}Be/{tot-b-be}N"}

def sentiment_agent(ticker, other_signals=None, **kwargs) -> dict:
    sigs = [v.get("signal") for v in (other_signals or {}).values() if isinstance(v, dict) and v.get("signal")]
    if not sigs: return {"signal":"neutral","confidence":0,"reasoning":"no other signals"}
    br = sigs.count("bullish") / len(sigs); ber = sigs.count("bearish") / len(sigs)
    if br > 0.7: return {"signal":"bearish","confidence":70,"reasoning":f"contrarian: {br:.0%} bullish"}
    if ber > 0.7: return {"signal":"bullish","confidence":70,"reasoning":f"contrarian: {ber:.0%} bearish"}
    return {"signal":"neutral","confidence":50,"reasoning":"mixed"}


# ---------------------------------------------------------------------------
# AGENT_REGISTRY: key → function
# ---------------------------------------------------------------------------

AGENT_REGISTRY = {
    "warren_buffett": warren_buffett_agent,
    "ben_graham": ben_graham_agent,
    "peter_lynch": peter_lynch_agent,
    "nassim_taleb": nassim_taleb_agent,
    "aswath_damodaran": aswath_damodaran_agent,
    "bill_ackman": bill_ackman_agent,
    "cathie_wood": cathie_wood_agent,
    "charlie_munger": charlie_munger_agent,
    "michael_burry": michael_burry_agent,
    "mohnish_pabrai": mohnish_pabrai_agent,
    "phil_fisher": phil_fisher_agent,
    "rakesh_jhunjhunwala": rakesh_jhunjhunwala_agent,
    "stanley_druckenmiller": stanley_druckenmiller_agent,
    "technical_analyst": technicals_agent,
    "fundamentals_analyst": fundamentals_agent,
    "growth_analyst": growth_agent,
    "news_sentiment_analyst": news_sentiment_agent,
    "sentiment_analyst": sentiment_agent,
    "valuation_analyst": valuation_agent,
}
