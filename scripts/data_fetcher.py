"""data_fetcher.py — 用 westock-data / neodata 替代 financial-datasets API

复现原项目 src/tools/api.py 的 6 个函数：
    get_prices / get_financial_metrics / search_line_items /
    get_insider_trades / get_company_news / get_market_cap

加上 ticker 转换 + JSON 缓存层 + markdown 表格解析。

调用方式（Python 脚本）:
    from data_fetcher import get_prices, get_financial_metrics, ...
    prices = get_prices("AAPL", "2026-01-01", "2026-07-24")
    metrics = get_financial_metrics("hk00700", "2026-07-24", period="ttm")

CLI 调用方式（westock-data 已在 builtin-skills 安装）:
    cd "/d/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills/westock-data"
    node scripts/index.js <command>
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量 / 路径
# ---------------------------------------------------------------------------

# skill 自带的本地 JSON 缓存（与原 financial-datasets 缓存行为一致）
SKILL_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_ROOT / "data_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

WESTOCK_DIR = (
    Path("D:/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills/westock-data")
    if Path("D:/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills/westock-data").exists()
    else None
)

# 缓存 TTL（秒）：行情 / 财务 / 新闻 / 股东
TTL = {
    "prices": 86400,           # 1 天
    "financial_metrics": 604800,  # 7 天
    "line_items": 604800,
    "insider": 604800,
    "news": 86400,
    "market_cap": 86400,
    "company_facts": 2592000,  # 30 天
}

# westock-data 输出里常见的中文列名 → 标准英文字段映射
# 数据最终会暴露给 LLM 看，所以保留原始中文字段名也 OK；但下划线版方便程序读取
COL_ALIAS = {
    # zhsy（利润表）列
    "营业收入": "OperatingRevenue",
    "OperatingRevenue": "OperatingRevenue",
    "净利润": "NetProfit",
    "NetProfit": "NetProfit",
    "EPS": "EPS",
    "EPSBasic": "BasicEPS",
    "BasicEPS": "BasicEPS",
    "毛利率": "GrossIncomeRatio",
    "GrossIncomeRatio": "GrossIncomeRatio",
    "净利率": "NetProfitRatio",
    "NetProfitRatio": "NetProfitRatio",
    "营业利润率": "OperatingProfitRatio",
    "OperatingProfitRatio": "OperatingProfitRatio",
    "ROE": "ROEWeighted",
    "ROEWeighted": "ROEWeighted",
    "ROA": "ROA",
    # zcfz（资产负债表）列
    "总资产": "TotalAssets",
    "TotalAssets": "TotalAssets",
    "总负债": "TotalLiability",
    "TotalLiability": "TotalLiability",
    "流动资产": "TotalCurrentAssets",
    "TotalCurrentAssets": "TotalCurrentAssets",
    "流动负债": "TotalCurrentLiability",
    "TotalCurrentLiability": "TotalCurrentLiability",
    "股东权益": "TotalEquity",
    "TotalEquity": "TotalEquity",
    "货币资金": "Cash",
    "Cash": "Cash",
    "每股净资产": "NetAssetPS",
    "NetAssetPS": "NetAssetPS",
    "流动比率": "CurrentRatio",
    "CurrentRatio": "CurrentRatio",
    "资产负债率": "DebtAssetsRatio",
    "DebtAssetsRatio": "DebtAssetsRatio",
    "速动比率": "QuickRatio",
    "QuickRatio": "QuickRatio",
    # xjll（现金流）列
    "经营现金流": "OperCashFlowPS",
    "OperCashFlowPS": "OperCashFlowPS",
    "CashflowPS": "CashflowPS",
    "自由现金流": "FCFPS",
    "FCFPS": "FCFPS",
}


# ---------------------------------------------------------------------------
# Ticker 转换
# ---------------------------------------------------------------------------

def ticker_to_westock(ticker: str) -> str:
    """把任意用户输入的 ticker 转成 westock-data 用的代码。

    支持格式：
      AAPL, MSFT, NVDA            → usAAPL / usMSFT / usNVDA
      600519.SH / 600519.SS       → sh600519
      000001.SZ                   → sz000001
      00700.HK / 0700.HK          → hk00700
      830799.BJ                   → bj830799
      已有正确格式 usAAPL          → 原样返回
      hk00700 / sh600519          → 原样返回
    """
    t = ticker.strip().upper()
    if not t:
        return t
    # 已经有 westock 前缀（usX / shX / szX / hkX / bjX）
    if re.match(r"^(US|SH|SZ|HK|BJ)\d+", t) or t.startswith("US"):
        return t
    # 拆 .SH / .SZ / .BJ / .SS / .HK
    m = re.match(r"^(\d{6})\.(SH|SZ|BJ|SS)$", t)
    if m:
        code, market = m.group(1), m.group(2)
        market_map = {"SH": "sh", "SS": "sh", "SZ": "sz", "BJ": "bj"}
        return f"{market_map[market]}{code}"
    m = re.match(r"^(\d{4,5})\.HK$", t)
    if m:
        return f"hk{m.group(1).zfill(5)}"
    # 美股：纯字母代码
    if re.match(r"^[A-Z]+$", t):
        return f"us{t}"
    return t


# ---------------------------------------------------------------------------
# 缓存层
# ---------------------------------------------------------------------------

def _cache_key(kind: str, *parts: Any) -> str:
    """生成缓存 key；parts 超过长度时用 hash 截断（避免 Windows 255 字符路径限制）。"""
    import hashlib
    parts_str = "_".join(str(p) for p in parts)
    if len(parts_str) > 100:
        parts_str = hashlib.md5(parts_str.encode("utf-8")).hexdigest()
    return f"{kind}__{parts_str}"


def _cache_get(key: str, ttl: int) -> Any | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ts = payload.get("_cached_at", 0)
        if time.time() - ts > ttl:
            return None
        return payload.get("data")
    except Exception:
        return None


def _cache_set(key: str, data: Any) -> None:
    path = CACHE_DIR / f"{key}.json"
    try:
        path.write_text(
            json.dumps({"_cached_at": time.time(), "data": data}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[cache] write {path} failed: {e}")


# ---------------------------------------------------------------------------
# 通用：subprocess 调 westock-data + markdown 解析
# ---------------------------------------------------------------------------

def _run_westock(args: list[str], timeout: int = 60) -> str:
    """调用 westock-data 命令，返回 stdout 文本。"""
    if WESTOCK_DIR is None:
        raise RuntimeError(
            "westock-data 未安装。应在 D:/WorkBuddy/resources/app.asar.unpacked/.../westock-data"
        )
    cmd = ["node", "scripts/index.js", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(WESTOCK_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        print(f"[westock] timeout: {' '.join(args[:3])}...")
        return ""
    except FileNotFoundError:
        print(f"[westock] node not found in PATH")
        return ""


def _parse_md_table(table_text: str) -> list[dict]:
    """解析 westock-data 输出的 markdown 表格，返回 list of dict。

    格式：
        | a | b | c |
        | --- | --- | --- |
        | 1 | 2 | 3 |
        | 4 | 5 | 6 |

    鲁棒性处理：
      - 行内换行（cell 里有 \\n  + 后续行是 cell 内容续行）：把续行 cell 拼到上一个
      - 表头行 + 分隔行 + 数据行严格分离
    """
    # 先按" | "拆 header，按 行 拆 data
    raw_lines = [ln for ln in table_text.strip().splitlines() if ln.strip()]
    # 把所有 cell 行收齐（行内可能换行）
    cell_lines = []
    for ln in raw_lines:
        if not ln.lstrip().startswith("|"):
            continue
        cell_lines.append(ln)

    if len(cell_lines) < 2:
        return []

    # 找 header（cell 数最多的那行）—— 数据行可能因 cell 跨行被切短
    parsed_rows = []
    for ln in cell_lines:
        if all(re.match(r"^:?-+:?$", c.strip()) for c in ln.strip().split("|")[1:-1]):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        parsed_rows.append(cells)

    if not parsed_rows:
        return []

    # 第一行 cell 数最多的当 header
    header_idx = max(range(len(parsed_rows)), key=lambda i: len(parsed_rows[i]))
    headers = parsed_rows[header_idx]
    header_n = len(headers)

    # 数据行：剩余所有；如果 cell 数 > header 数，认为是上一行的续行，拼接到上一行末尾 cell
    data_rows_raw = parsed_rows[:header_idx] + parsed_rows[header_idx + 1:]
    data_rows = []
    for row in data_rows_raw:
        if len(row) < header_n:
            row = row + [""] * (header_n - len(row))
        elif len(row) > header_n:
            # 多出来的 cell 拼到最后一个 cell
            extra = " ".join(row[header_n - 1:])
            row = row[:header_n - 1] + [extra]
        # 把上一行的最后一个 cell 接续到本行第一个 cell（如果本行 cell 数 == header 但看起来像续行）
        data_rows.append(row)

    # 转成 dict list
    return [dict(zip(headers, row)) for row in data_rows]


def _extract_all_tables(stdout: str) -> list[list[dict]]:
    """从一段 westock-data 输出里抽出所有 markdown 表格块。

    westock-data 会输出多张表（每张表前面有一个 **表名** 标题）。
    """
    chunks = re.split(r"(?m)^\*\*[^*]+\*\*\s*$", stdout)
    tables = []
    for ch in chunks:
        parsed = _parse_md_table(ch)
        if parsed:
            tables.append(parsed)
    if not tables:
        parsed = _parse_md_table(stdout)
        if parsed:
            tables = [parsed]
    return tables


# ---------------------------------------------------------------------------
# 6 个 API 替代函数（按 financial-datasets 风格）
# ---------------------------------------------------------------------------

def get_prices(ticker: str, start_date: str, end_date: str, api_key: str | None = None) -> list[dict]:
    """替代 financial-datasets /prices/.

    Returns:
        list of {open, close, high, low, volume, time}
    """
    wt = ticker_to_westock(ticker)
    key = _cache_key("prices", wt, start_date, end_date)
    cached = _cache_get(key, TTL["prices"])
    if cached is not None:
        return cached

    # westock-data 用 start/end 优先级高于 limit
    out = _run_westock(["kline", wt, "--period", "day", "--start", start_date, "--end", end_date], timeout=30)
    tables = _extract_all_tables(out)
    if not tables:
        _cache_set(key, [])
        return []

    rows = tables[0]
    prices = []
    for r in rows:
        try:
            prices.append({
                "open": float(r.get("open", 0) or 0),
                "close": float(r.get("last", r.get("close", 0)) or 0),
                "high": float(r.get("high", 0) or 0),
                "low": float(r.get("low", 0) or 0),
                "volume": int(float(r.get("volume", 0) or 0)),
                "time": r.get("date", ""),
            })
        except Exception:
            continue
    # 按时间升序
    prices.sort(key=lambda x: x["time"])
    _cache_set(key, prices)
    return prices


def _westock_market_cap_quote(ticker: str) -> dict | None:
    """从 quote 命令读 PE/PB/市值/流通股。"""
    wt = ticker_to_westock(ticker)
    key = _cache_key("quote", wt)
    cached = _cache_get(key, TTL["market_cap"])
    if cached is not None:
        return cached

    out = _run_westock(["quote", wt], timeout=30)
    tables = _extract_all_tables(out)
    if not tables or not tables[0]:
        _cache_set(key, None)
        return None
    row = tables[0][0]
    quote_data = {
        "price": _try_float(row.get("price")),
        "prev_close": _try_float(row.get("prev_close")),
        "open": _try_float(row.get("open")),
        "high": _try_float(row.get("high")),
        "low": _try_float(row.get("low")),
        "volume": _try_float(row.get("volume")),
        "amount": _try_float(row.get("amount")),
        "change_pct": _try_float(row.get("change_percent")),
        # 估值 / 股本
        "pe_ratio": _try_float(row.get("pe_ratio")),
        "pb_ratio": _try_float(row.get("pb_ratio")),
        "ps_ratio": _try_float(row.get("ps_ratio")),
        "dividend_ratio_ttm": _try_float(row.get("dividend_ratio_ttm")),
        "dividend_ttm": _try_float(row.get("dividend_ttm")),
        # 市值：westock-data 单位是"亿元"，转成"元"
        "total_market_cap_yi": _try_float(row.get("total_market_cap")),  # 亿
        "total_market_cap": (_try_float(row.get("total_market_cap")) or 0) * 1e8,
        "circulating_market_cap": (_try_float(row.get("circulating_market_cap")) or 0) * 1e8,
        "total_shares": _try_float(row.get("total_shares")),
        "float_shares": _try_float(row.get("float_shares")),
        # 历史
        "high_52week": _try_float(row.get("high_52week")),
        "low_52week": _try_float(row.get("low_52week")),
        "chg_5d": _try_float(row.get("chg_5d")),
        "chg_20d": _try_float(row.get("chg_20d")),
        "chg_60d": _try_float(row.get("chg_60d")),
        "chg_ytd": _try_float(row.get("chg_ytd")),
    }
    _cache_set(key, quote_data)
    return quote_data


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
) -> list[dict]:
    """替代 financial-datasets /financial-metrics/.

    Returns:
        list of FinancialMetrics dict（最新在前）

    适配 westock-data 的差异：
      - 港股：finance 输出 zhsy / zcfz / xjll，zhsy 含所有比率
      - A 股：finance 输出 lrb / zcfz / xjll，比率要自己从 zcfz 算
      - 美股：finance 输出 us_xxx（待测试）
    """
    wt = ticker_to_westock(ticker)
    key = _cache_key("fmetrics", wt, end_date, period, limit)
    cached = _cache_get(key, TTL["financial_metrics"])
    if cached is not None:
        return cached

    out = _run_westock(["finance", wt, "--num", str(max(limit, 4))], timeout=30)
    tables = _extract_all_tables(out)
    if not tables:
        _cache_set(key, [])
        return []

    # 自动识别哪个表是利润 / 资负 / 现金流
    income_table = None      # 利润表
    balance_table = None     # 资负表
    cashflow_table = None    # 现金流表

    for tbl in tables:
        first_row = tbl[0] if tbl else {}
        keys = set(first_row.keys())
        # 利润表特征：含 BasicEPS 或 OperatingRevenue 或 OperatingIncome
        if not income_table and ({"BasicEPS", "BasicEPS_Q", "EPS"} & keys) and (
            {"OperatingRevenue", "OperatingIncome"} & keys or "NetProfit" in keys or "ProfitToShareholders" in keys
        ):
            income_table = tbl
        # 资负表特征：含 TotalAssets 或 TotalCurrentAssets
        elif not balance_table and (
            {"TotalAssets", "TotalCurrentAssets"} & keys or "TotalShareholderEquity" in keys
        ):
            balance_table = tbl
        # 现金流表特征：含 CFO 或 NetOperateCashFlow
        elif not cashflow_table and (
            {"CFO", "CFF", "CFI"} & keys or "NetOperateCashFlow" in keys or "FCFF" in keys
        ):
            cashflow_table = tbl

    if not income_table and tables:
        income_table = tables[0]
    if not balance_table and len(tables) >= 2:
        balance_table = tables[1]
    if not cashflow_table and len(tables) >= 3:
        cashflow_table = tables[2]

    quote = _westock_market_cap_quote(ticker) or {}

    metrics = []
    for r in (income_table or []):
        # 取对应期号的 balance 数据（如果 date 对得上）
        period_date = r.get("_date", r.get("EndDate", ""))
        balance_row = None
        if balance_table and period_date:
            for br in balance_table:
                if br.get("_date", br.get("EndDate", "")) == period_date:
                    balance_row = br
                    break
            if not balance_row and balance_table:
                balance_row = balance_table[0]
        cashflow_row = None
        if cashflow_table and period_date:
            for cr in cashflow_table:
                if cr.get("_date", cr.get("EndDate", "")) == period_date:
                    cashflow_row = cr
                    break
            if not cashflow_row and cashflow_table:
                cashflow_row = cashflow_table[0]

        # === 百分数 / 比率 ===
        # 港股 zhsy: GrossIncomeRatio=毛利率%
        # A 股 lrb:  无毛利率字段，需从营收+营业利润算
        # 美股 income: GrossMargin=毛利率%
        gross_margin = None
        for k in ["GrossIncomeRatio", "GrossMargin", "GrossMargin_Q"]:
            v = _try_float(r.get(k))
            if v is not None:
                gross_margin = v / 100
                break
        if gross_margin is None:
            rev = _try_float(r.get("OperatingRevenue") or r.get("TotalOperatingRevenue") or r.get("Sales"))
            op_profit = _try_float(r.get("OperatingProfit"))
            if rev and rev > 0 and op_profit is not None:
                gross_margin = op_profit / rev  # 近似

        op_margin = None
        for k in ["OperatingProfitRatio", "OperatingMargin", "OperatingMargin_Q"]:
            v = _try_float(r.get(k))
            if v is not None:
                op_margin = v / 100
                break
        if op_margin is None:
            rev = _try_float(r.get("OperatingRevenue") or r.get("TotalOperatingRevenue") or r.get("Sales"))
            op_profit = _try_float(r.get("OperatingProfit"))
            if rev and rev > 0 and op_profit is not None:
                op_margin = op_profit / rev

        net_margin = None
        for k in ["NetProfitRatio", "NetMargin", "NetMargin_Q"]:
            v = _try_float(r.get(k))
            if v is not None:
                net_margin = v / 100
                break
        if net_margin is None:
            rev = _try_float(r.get("OperatingRevenue") or r.get("TotalOperatingRevenue") or r.get("Sales"))
            ni_field = r.get("ProfitToShareholders") or r.get("NPParentCompanyOwners") or r.get("NetIncome")
            ni = _try_float(ni_field)
            if rev and rev > 0 and ni is not None:
                net_margin = ni / rev

        # ROE — 可能在 income 也可能在 balance
        roe = None
        for src_row in [r, balance_row or {}]:
            for k in ["RoeWeighted", "ROE", "ROEWeighted"]:
                v = _try_float(src_row.get(k))
                if v is not None:
                    roe = v / 100
                    break
            if roe is not None:
                break
        if roe is None and balance_row:
            ni_field = r.get("ProfitToShareholders") or r.get("NPParentCompanyOwners") or r.get("NetIncome")
            ni = _try_float(ni_field)
            eq_field = (balance_row.get("TotalShareholderEquity") or balance_row.get("TotalEquity")
                        or balance_row.get("ShareHolderEquity") or balance_row.get("CommonStockEquity"))
            eq = _try_float(eq_field)
            if ni and eq and eq > 0:
                roe = ni / eq

        roa = None
        for src_row in [r, balance_row or {}]:
            for k in ["ROA"]:
                v = _try_float(src_row.get(k))
                if v is not None:
                    roa = v / 100
                    break
            if roa is not None:
                break
        if roa is None and balance_row:
            ni_field = r.get("ProfitToShareholders") or r.get("NPParentCompanyOwners") or r.get("NetIncome")
            ni = _try_float(ni_field)
            ta = _try_float(balance_row.get("TotalAssets"))
            if ni and ta and ta > 0:
                roa = ni / ta

        # CurrentRatio / QuickRatio — 通常在 balance 表
        cr = None
        qr = None
        if balance_row:
            cr = _try_float(balance_row.get("CurrentRatio"))
            if cr is None:
                ca = _try_float(balance_row.get("TotalCurrentAssets") or balance_row.get("CurrentAssets"))
                cl = _try_float(balance_row.get("TotalCurrentLiability") or balance_row.get("CurrentLiabilities"))
                if ca and cl and cl > 0:
                    cr = ca / cl
            qr = _try_float(balance_row.get("QuickRatio"))

        # D/E — 必须算：westock-data 没有现成的 DebtEquityRatio 字段
        # 注：LiabilityToAsset 是 D/A 不是 D/E，别混用
        de = None
        for src_row in [r, balance_row or {}]:
            for k in ["DebtEquityRatio"]:
                v = _try_float(src_row.get(k))
                if v is not None:
                    de = v / 100
                    break
            if de is not None:
                break
        if de is None and balance_row:
            tl = _try_float(balance_row.get("TotalLiability") or balance_row.get("TotalLiabilities"))
            eq_field = (balance_row.get("TotalShareholderEquity") or balance_row.get("TotalEquity")
                        or balance_row.get("ShareHolderEquity") or balance_row.get("CommonStockEquity"))
            eq = _try_float(eq_field)
            if tl and eq and eq > 0:
                de = tl / eq

        da = None
        if balance_row:
            da = _try_float(balance_row.get("LiabilityToAsset") or balance_row.get("DebtAssetsRatio"))
            if da is not None:
                da = da / 100
            else:
                tl = _try_float(balance_row.get("TotalLiability") or balance_row.get("TotalLiabilities"))
                ta = _try_float(balance_row.get("TotalAssets"))
                if tl and ta and ta > 0:
                    da = tl / ta

        # Growth — 只拿 YoY 字段，不能把 TTM 绝对值当增长率
        rev_g = _try_float(r.get("OperatingRevenueGr1y"))
        eg = _try_float(r.get("NetProfitGr1y") or r.get("NpParentCompanyGr1y"))
        bg = _try_float(r.get("TotalAssetGr1y"))

        m = {
            "ticker": wt,
            "report_period": period_date,
            "period": r.get("PeriodMark", ""),
            "currency": r.get("CurrencyType", ""),
            "currency_unit": r.get("CurrencyUnit", ""),
            # === 估值（从 quote 拿） ===
            "market_cap": quote.get("total_market_cap"),
            "price_to_earnings_ratio": quote.get("pe_ratio"),
            "price_to_book_ratio": quote.get("pb_ratio"),
            "price_to_sales_ratio": quote.get("ps_ratio"),
            "enterprise_value": None,
            "enterprise_value_to_ebitda_ratio": None,
            "free_cash_flow_yield": None,
            "peg_ratio": None,
            # === 盈利 / 利润率 ===
            "gross_margin": gross_margin,
            "operating_margin": op_margin,
            "net_margin": net_margin,
            "return_on_equity": roe,
            "return_on_assets": roa,
            "return_on_invested_capital": None,
            # === 偿债能力 ===
            "current_ratio": cr,
            "quick_ratio": qr,
            "debt_to_equity": de,
            "debt_to_assets": da,
            "interest_coverage": None,
            # === 增长率 ===
            "revenue_growth": (rev_g / 100) if rev_g is not None and abs(rev_g) > 1.5 else rev_g,
            "earnings_growth": (eg / 100) if eg is not None and abs(eg) > 1.5 else eg,
            "book_value_growth": (bg / 100) if bg is not None and abs(bg) > 1.5 else bg,
            "earnings_per_share_growth": None,
            "free_cash_flow_growth": None,
            "operating_income_growth": _try_float(r.get("OperProfitGr1y")),
            "ebitda_growth": None,
            "payout_ratio": None,
            # === 每股数据 ===
            "earnings_per_share": _try_float(r.get("BasicEPS") or r.get("BasicEPS_Q") or r.get("EPS")),
            "book_value_per_share": _try_float(r.get("NetAssetPS") or r.get("BPS")),
            "free_cash_flow_per_share": _try_float(r.get("CashflowPS", r.get("OperCashFlowPS"))),
            # 原始字段保留
            "_raw": r,
        }
        metrics.append(m)
    _cache_set(key, metrics)
    return metrics


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
) -> list[dict]:
    """替代 financial-datasets /financials/search/line-items.

    westock-data finance 返回 3 张表（利润 / 资负 / 现金流），覆盖绝大部分 line_items。
    """
    wt = ticker_to_westock(ticker)
    key = _cache_key("lineitems", wt, ",".join(sorted(line_items)), end_date, period, limit)
    cached = _cache_get(key, TTL["line_items"])
    if cached is not None:
        return cached

    out = _run_westock(["finance", wt, "--num", str(max(limit, 4))], timeout=30)
    tables = _extract_all_tables(out)
    # 把 3 张表按 zhsy / zcfz / xjll 命名
    table_names = []
    if len(tables) >= 1:
        table_names.append("zhsy")
    if len(tables) >= 2:
        table_names.append("zcfz")
    if len(tables) >= 3:
        table_names.append("xjll")

    merged: dict[str, dict] = {}  # report_period → 行
    for tname, trows in zip(table_names, tables):
        for r in trows:
            period_key = r.get("_date", r.get("EndDate", ""))
            if period_key not in merged:
                merged[period_key] = {"ticker": wt, "report_period": period_key,
                                       "period": r.get("PeriodMark", ""),
                                       "currency": r.get("CurrencyType", "")}
            # 字段写入
            for k, v in r.items():
                merged[period_key][k] = v

    # 字段别名映射：跨 A 股 / 港股 / 美股共用一套
    # 港股 zhsy: OperatingIncome=营收, ProfitToShareholders=归母, NetAssetPS=每股净资产
    # A 股 lrb:  OperatingRevenue=营收, NPParentCompanyOwners=归母, 没 NetAssetPS 用 zcfz
    field_map = {
        "revenue": ["OperatingIncome", "OperatingRevenue", "TotalOperatingRevenue"],
        "net_income": ["ProfitToShareholders", "NPParentCompanyOwners", "NPParentCompanyOwnersTTM", "EarningAfterTax"],
        "earnings_per_share": ["BasicEPS", "EPS", "DilutedEPS"],
        "book_value_per_share": ["NetAssetPS"],  # A 股没有，留 None → agent 跳过
        "total_assets": ["TotalAssets"],
        "total_liabilities": ["TotalLiability"],
        "current_assets": ["TotalCurrentAssets", "CurrentAssetstota"],
        "current_liabilities": ["TotalCurrentLiability", "CurrentLiabilitytotl"],
        "dividends_and_other_cash_distributions": ["DividendDistribution"],
        "outstanding_shares": ["TotalShares", "CirculationShares"],
        "free_cash_flow": ["FreeCashFlow", "CFF", "FCFF"],
        "operating_income": ["OperatingProfit"],
        "depreciation_and_amortization": ["DepreciationAmortization"],
        "capital_expenditure": ["CapitalExpenditure", "Purcapitalassents"],
        "working_capital": ["WorkingCapital"],
        "cash_and_equivalents": ["Cash", "Endperiodce", "BeginPeriodCash", "CashEquivalents"],
        "total_debt": ["TotalDebt", "InterestBearDebt", "ShortTermLoan", "LongTermLoan"],
        "interest_expense": ["FinancialCost", "FinancialExpense"],
        "ebit": ["OperatingProfit", "EBIT"],
        "ebitda": ["EBITDA"],
        "gross_profit": ["GrossIncome", "GrossProfit", "GrossProfitTTM"],
        "shareholders_equity": ["TotalEquity", "SeWithoutMinority", "TotalShareholderEquity"],
    }
    # 给 line_items 期望的字段填入（即使为 None）
    results = []
    for period_key, row in merged.items():
        result_row = {
            "ticker": wt,
            "report_period": period_key,
            "period": row.get("period", ""),
            "currency": row.get("currency", ""),
            # 平铺常用字段
            "revenue": _pick(row, field_map["revenue"]),
            "net_income": _pick(row, field_map["net_income"]),
            "earnings_per_share": _pick(row, field_map["earnings_per_share"]),
            "book_value_per_share": _pick(row, field_map["book_value_per_share"]),
            "total_assets": _pick(row, field_map["total_assets"]),
            "total_liabilities": _pick(row, field_map["total_liabilities"]),
            "current_assets": _pick(row, field_map["current_assets"]),
            "current_liabilities": _pick(row, field_map["current_liabilities"]),
            "outstanding_shares": _pick(row, field_map["outstanding_shares"]),
            "free_cash_flow": _pick(row, field_map["free_cash_flow"]),
            "operating_income": _pick(row, field_map["operating_income"]),
            "depreciation_and_amortization": _pick(row, field_map["depreciation_and_amortization"]),
            "capital_expenditure": _pick(row, field_map["capital_expenditure"]),
            "working_capital": _pick(row, field_map["working_capital"]),
            "cash_and_equivalents": _pick(row, field_map["cash_and_equivalents"]),
            "total_debt": _pick(row, field_map["total_debt"]),
            "interest_expense": _pick(row, field_map["interest_expense"]),
            "ebit": _pick(row, field_map["ebit"]),
            "ebitda": _pick(row, field_map["ebitda"]),
            "gross_profit": _pick(row, field_map["gross_profit"]),
            "shareholders_equity": _pick(row, field_map["shareholders_equity"]),
            "_raw": row,
        }
        results.append(result_row)
    results.sort(key=lambda x: x["report_period"], reverse=True)
    _cache_set(key, results[:limit])
    return results[:limit]


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
) -> list[dict]:
    """替代 financial-datasets /insider-trades/.

    westock-data 没有直接给 insider_trades；用 shareholder + notice 拼接：
      - shareholder → 当前大股东
      - notice list → 大股东 / 董监高增减持公告
    """
    wt = ticker_to_westock(ticker)
    key = _cache_key("insider", wt, start_date or "none", end_date, limit)
    cached = _cache_get(key, TTL["insider"])
    if cached is not None:
        return cached

    # 拉股东信息（用于判断 skin in game）
    out = _run_westock(["shareholder", wt], timeout=30)
    shareholders = []
    if out:
        # 解析**持股股东信息** 表
        tables = _extract_all_tables(out)
        for tbl in tables:
            for r in tbl:
                if "name" in r and "pct" in r:
                    shareholders.append({
                        "name": r.get("name", ""),
                        "shares": _try_float(r.get("shares")),
                        "pct": _try_float(r.get("pct")),
                    })

    # 拉公告（关键词过滤：增 / 减 / 回购）
    notice_out = _run_westock(["notice", "list", wt, "--limit", "20"], timeout=30)
    tables = _extract_all_tables(notice_out)
    insider_events = []
    for tbl in tables:
        for r in tbl:
            title = r.get("title", "")
            if any(kw in title for kw in ["增持", "减持", "回购", "回购股份", "股份回购", "股本变动", "证券变动"]):
                insider_events.append({
                    "title": title,
                    "date": r.get("time", ""),
                    "url": r.get("url", ""),
                })

    # 组合为简化版的 insider_trades（不构造 transaction_shares；用于 agent skin-in-game 判断）
    result = {
        "shareholders": shareholders[:20],
        "insider_events": insider_events[:20],
        "note": "westock-data 没有完整 transaction_shares / transaction_price 数据；"
                 "skin-in-game 信号由大股东持股比例 + 增减持公告代理",
    }
    _cache_set(key, result)
    # 为了兼容原接口，仍然返回 list（但每个元素不是交易，是事件）
    return result  # 注意：返回的是 dict 不是 list，agent 需要适配


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
) -> list[dict]:
    """替代 financial-datasets /news/.

    westock-data news 命令在当前渠道不可用；改用 report + notice 拼接。
    """
    wt = ticker_to_westock(ticker)
    key = _cache_key("news", wt, start_date or "none", end_date, limit)
    cached = _cache_get(key, TTL["news"])
    if cached is not None:
        return cached

    news_items = []

    # 研报（机构观点）
    out = _run_westock(["report", wt, "--limit", "20"], timeout=30)
    tables = _extract_all_tables(out)
    for tbl in tables:
        for r in tbl:
            t = r.get("title", "")
            if not t:
                continue
            # 简单情感判定（标题关键词）
            sentiment = _naive_sentiment(t)
            news_items.append({
                "ticker": wt,
                "title": t,
                "source": r.get("src", r.get("srcShort", "研报")),
                "date": r.get("time", "")[:10] if r.get("time") else "",
                "url": r.get("url", ""),
                "sentiment": sentiment,
                "type": "research_report",
            })

    # 公告
    notice_out = _run_westock(["notice", "list", wt, "--limit", "20"], timeout=30)
    tables = _extract_all_tables(notice_out)
    for tbl in tables:
        for r in tbl:
            t = r.get("title", "")
            if not t:
                continue
            news_items.append({
                "ticker": wt,
                "title": t,
                "source": "公司公告",
                "date": r.get("time", "")[:10] if r.get("time") else "",
                "url": r.get("url", ""),
                "sentiment": _naive_sentiment(t),
                "type": "company_notice",
            })

    # 按日期降序
    news_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    news_items = news_items[:limit]
    _cache_set(key, news_items)
    return news_items


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str | None = None,
) -> float | None:
    """替代 financial-datasets market cap（用 quote 的 total_market_cap，单位是元）。"""
    quote = _westock_market_cap_quote(ticker)
    if quote and quote.get("total_market_cap"):
        return quote["total_market_cap"]
    # 退到 finance
    metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=1)
    if metrics and metrics[0].get("market_cap"):
        return metrics[0]["market_cap"]
    return None


def get_company_facts(ticker: str, api_key: str | None = None) -> dict | None:
    """替代 financial-datasets /company/facts/（用 profile）."""
    wt = ticker_to_westock(ticker)
    key = _cache_key("facts", wt)
    cached = _cache_get(key, TTL["company_facts"])
    if cached is not None:
        return cached

    out = _run_westock(["profile", wt], timeout=30)
    tables = _extract_all_tables(out)
    if not tables or not tables[0]:
        _cache_set(key, None)
        return None
    r = tables[0][0]
    facts = {
        "ticker": wt,
        "name": r.get("name", ""),
        "industry": r.get("industry", ""),
        "sector": r.get("industry", ""),
        "exchange": "",
        "listing_date": r.get("listedDate", ""),
        "website_url": r.get("website", ""),
        "description": (r.get("introduction", "") or "")[:500],
        "business": (r.get("business", "") or "")[:500],
    }
    _cache_set(key, facts)
    return facts


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _try_float(x: Any) -> float | None:
    if x is None or x == "" or x == "-":
        return None
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def _pick(row: dict, keys: list[str]) -> Any:
    """从 row 里按 keys 顺序取第一个非空值。"""
    for k in keys:
        v = row.get(k)
        if v is not None and v != "" and v != "-":
            return v
    return None


def _naive_sentiment(text: str) -> str:
    """基于关键词的新闻情感判定（中文 + 英文）。"""
    t = text.lower()
    positive = [
        "增持", "上调", "买入", "推荐", "超预期", "增长", "看好", "积极",
        "buy", "outperform", "bullish", "upgrade", "raise", "beat", "strong",
    ]
    negative = [
        "减持", "下调", "卖出", "不及预期", "下滑", "亏损", "诉讼", "召回", "调查",
        "sell", "underperform", "bearish", "downgrade", "cut", "miss", "weak",
    ]
    pos = sum(1 for k in positive if k in t)
    neg = sum(1 for k in negative if k in t)
    if pos > neg:
        return "bullish"
    if neg > pos:
        return "bearish"
    return "neutral"


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== data_fetcher 自测 ===")
    print(f"westock_dir = {WESTOCK_DIR}")
    print(f"cache_dir   = {CACHE_DIR}")

    wt = ticker_to_westock("AAPL")
    print(f"\nAAPL → {wt}")

    wt = ticker_to_westock("600519.SH")
    print(f"600519.SH → {wt}")

    wt = ticker_to_westock("00700.HK")
    print(f"00700.HK → {wt}")

    print("\n--- get_prices(hk00700, 最近 30 天) ---")
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    prices = get_prices("00700.HK", start, end)
    print(f"  拿到 {len(prices)} 条，最近 3 条：")
    for p in prices[-3:]:
        print(f"  {p}")

    print("\n--- get_financial_metrics(hk00700) ---")
    metrics = get_financial_metrics("00700.HK", end)
    print(f"  拿到 {len(metrics)} 期，最新一期：")
    if metrics:
        m = metrics[0]
        print(f"  PE={m['price_to_earnings_ratio']}, ROE={m['return_on_equity']}, "
              f"current_ratio={m['current_ratio']}, D/E={m['debt_to_equity']}, "
              f"revenue_growth={m['revenue_growth']}")

    print("\n--- search_line_items(hk00700, [revenue, net_income]) ---")
    items = search_line_items("00700.HK", ["revenue", "net_income"], end, limit=2)
    print(f"  拿到 {len(items)} 期")
    if items:
        print(f"  revenue={items[0].get('revenue')}, net_income={items[0].get('net_income')}")

    print("\n--- get_market_cap(hk00700) ---")
    mc = get_market_cap("00700.HK", end)
    print(f"  market_cap = {mc}")

    print("\n--- get_company_news(hk00700) ---")
    news = get_company_news("00700.HK", end, limit=5)
    print(f"  拿到 {len(news)} 条")
    for n in news[:3]:
        print(f"  [{n['date']}] [{n['sentiment']}] {n['title']}")

    print("\n--- get_company_facts(hk00700) ---")
    facts = get_company_facts("00700.HK")
    if facts:
        print(f"  name={facts.get('name')}, industry={facts.get('industry')}, listed={facts.get('listing_date')}")
    else:
        print("  facts = None")

    print("\n--- dump zhsy 第一行原始字段（看实际列名）---")
    import subprocess
    result = subprocess.run(
        ["node", "scripts/index.js", "finance", "hk00700", "--num", "1"],
        cwd=str(WESTOCK_DIR),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    tables = _extract_all_tables(result.stdout)
    if tables and tables[0]:
        print(f"  zhsy cols ({len(tables[0][0])}): {list(tables[0][0].keys())[:30]}...")
        print(f"  第一行 _date={tables[0][0].get('_date')}")

    print("\n=== done ===")