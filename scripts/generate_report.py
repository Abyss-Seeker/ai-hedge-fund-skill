"""generate_report.py — 从 run_fund.py 的 JSON 结果生成 PDF 报告

用法:
    python generate_report.py --input results/run_xxx.json --output results/report.pdf

依赖（自动检测）:
    fpdf2 (pip install fpdf2) — 首选
    如不可用，生成 HTML 替代
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


def _safe_str(val, max_len=200):
    s = str(val) if val is not None else "-"
    return s[:max_len]


def generate_html_report(data: dict, output_path: str) -> str:
    """生成 HTML 报告（fallback 模式或直接使用）。"""
    tickers = data.get("tickers", [])
    run_time = data.get("run_time", datetime.now().isoformat())
    signals = data.get("analyst_signals", {})
    risk = data.get("risk_data", {})
    decisions = data.get("decisions", {})

    # 摘要行
    summary_rows = ""
    for t in tickers:
        d = decisions.get(t, {})
        action = d.get("action", "-").upper()
        act_color = {"BUY": "#22c55e", "SELL": "#ef4444", "SHORT": "#ef4444",
                     "COVER": "#f59e0b", "HOLD": "#94a3b8"}.get(action, "#000")
        summary_rows += f"""
        <tr>
            <td><strong>{t}</strong></td>
            <td style="color:{act_color};font-weight:bold">{action}</td>
            <td>{d.get('quantity', 0)}</td>
            <td>{d.get('confidence', 0)}%</td>
            <td style="font-size:11px;word-wrap:break-word;max-width:320px">{d.get('reasoning', '-')[:200]}</td>
        </tr>"""

    # 信号矩阵
    signal_rows = ""
    agent_keys = [k for k in signals.keys() if k != "risk_management_agent"]
    for t in tickers:
        for ak in agent_keys:
            s = signals.get(ak, {}).get(t, {})
            sig = s.get("signal", "-")
            conf = s.get("confidence", 0)
            reason = s.get("reasoning", "-")[:200]
            color = {"bullish": "#22c55e", "bearish": "#ef4444", "neutral": "#94a3b8"}.get(sig, "#000")
            signal_rows += f"""
            <tr>
                <td>{t}</td>
                <td style="font-size:11px">{ak}</td>
                <td style="color:{color};font-weight:bold">{sig.upper()}</td>
                <td>{conf}%</td>
                <td style="font-size:10px;word-wrap:break-word;max-width:340px">{reason}</td>
            </tr>"""

    # 风险行
    risk_rows = ""
    for t in tickers:
        r = risk.get(t, {})
        vol = r.get("volatility_metrics", {})
        risk_rows += f"""
        <tr>
            <td>{t}</td>
            <td>{r.get('current_price', '-')}</td>
            <td>{r.get('remaining_position_limit', 0):,.0f}</td>
            <td>{vol.get('annualized_volatility', 0):.1%}</td>
            <td>{vol.get('data_points', 0)}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>AI Hedge Fund 分析报告</title>
<style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; max-width: 1000px; margin: auto; padding: 24px; color: #1e293b; }}
    .cover {{ text-align: center; padding: 40px 0 30px; border-bottom: 2px solid #e2e8f0; margin-bottom: 30px; }}
    .cover h1 {{ font-size: 32px; margin-bottom: 8px; }}
    .cover .brand {{ font-size: 14px; color: #6366f1; font-weight: 600; margin-bottom: 5px; }}
    .subtitle {{ text-align: center; color: #64748b; margin-bottom: 30px; font-size: 13px; }}
    h2 {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; margin-top: 36px; font-size: 18px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 24px; table-layout: fixed; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; overflow-wrap: break-word; word-break: break-all; }}
    th {{ background: #f1f5f9; font-weight: 600; font-size: 13px; }}
    td {{ font-size: 12px; vertical-align: top; }}
    .disclaimer {{ background: #fef3c7; border: 1px solid #f59e0b; padding: 16px; margin-top: 36px; border-radius: 8px; font-size: 13px; color: #92400e; }}
    .signature {{ text-align: center; color: #6366f1; font-size: 13px; font-weight: 600; margin-top: 30px; padding-top: 20px; border-top: 1px solid #e2e8f0; }}
    @media print {{ body {{ max-width: 100%; }} }}
</style>
</head>
<body>

<div class="cover">
    <div class="brand">AI Hedge Fund (WorkBuddy Edition @Tsukimori)</div>
    <h1>AI Hedge Fund 分析报告</h1>
    <p class="subtitle">生成时间: {run_time} | 分析标的: {', '.join(tickers)} | 分析师: {len(agent_keys)} 位</p>
</div>

<h2>一、最终决策摘要</h2>
<table>
    <colgroup><col style="width:12%"><col style="width:10%"><col style="width:8%"><col style="width:10%"><col style="width:60%"></colgroup>
    <tr><th>股票</th><th>操作</th><th>数量</th><th>置信度</th><th>理由</th></tr>
    {summary_rows}
</table>

<h2>二、分析师信号矩阵</h2>
<table>
    <colgroup><col style="width:10%"><col style="width:18%"><col style="width:8%"><col style="width:8%"><col style="width:56%"></colgroup>
    <tr><th>股票</th><th>分析师</th><th>信号</th><th>置信度</th><th>推理</th></tr>
    {signal_rows}
</table>

<h2>三、风险与仓位数据</h2>
<table>
    <colgroup><col style="width:15%"><col style="width:15%"><col style="width:20%"><col style="width:20%"><col style="width:15%"></colgroup>
    <tr><th>股票</th><th>当前价格</th><th>仓位上限</th><th>年化波动率</th><th>数据天数</th></tr>
    {risk_rows}
</table>

<div class="disclaimer">
    <strong>免责声明</strong><br>
    本报告由 AI Hedge Fund Skill (WorkBuddy Edition @Tsukimori) 自动生成，所有交易建议<b>仅用于研究和教育目的</b>，不构成投资建议。
    过去表现不代表未来结果。真实交易前请咨询持牌投资顾问。使用者自负盈亏。
</div>

<div class="signature">AI Hedge Fund (WorkBuddy Edition @Tsukimori) &mdash; github.com/Abyss-Seeker/ai-hedge-fund-skill</div>

</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return output_path


def generate_pdf_report(data: dict, output_path: str) -> str:
    """生成 PDF 报告（首选 fpdf2，fallback 到 HTML）。"""
    if not HAS_FPDF:
        html_path = output_path.replace(".pdf", ".html")
        generate_html_report(data, html_path)
        print(f"[report] fpdf2 未安装，已生成 HTML 替代: {html_path}")
        print("[report] 安装 fpdf2 以直接生成 PDF: pip install fpdf2")
        return html_path

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # 中文字体
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    font_loaded = False
    for fp in font_paths:
        if Path(fp).exists():
            try:
                pdf.add_font("zh", "", fp, uni=True)
                pdf.add_font("zh", "B", fp, uni=True)
                font_loaded = True
                break
            except Exception:
                continue

    if not font_loaded:
        html_path = output_path.replace(".pdf", ".html")
        print("[report] 未找到中文字体，已生成 HTML 替代")
        return generate_html_report(data, html_path)

    tickers = data.get("tickers", [])
    run_time = data.get("run_time", "")
    signals = data.get("analyst_signals", {})
    risk = data.get("risk_data", {})
    decisions = data.get("decisions", {})
    agent_keys = [k for k in signals.keys() if k != "risk_management_agent"]

    def write_title(text, size=18):
        pdf.set_font("zh", "B", size)
        pdf.cell(0, 12, text, ln=True)
        pdf.ln(4)

    def write_normal(text, size=9):
        pdf.set_font("zh", "", size)
        pdf.cell(0, 7, text, ln=True)

    def write_signature():
        pdf.ln(4)
        pdf.set_font("zh", "B", 10)
        pdf.cell(0, 8, "AI Hedge Fund (WorkBuddy Edition @Tsukimori)", ln=True, align="C")
        pdf.set_font("zh", "", 7)
        pdf.cell(0, 5, "github.com/Abyss-Seeker/ai-hedge-fund-skill", ln=True, align="C")

    def write_table_safe(headers, rows, col_widths, max_rows_per_page=35):
        """生成防溢出表格：用 multi_cell 做自动换行，行高自适应。
        每页最多 max_rows_per_page 行，超出自动分页。
        """
        n_rows = len(rows)
        for start in range(0, n_rows, max_rows_per_page):
            chunk = rows[start:start + max_rows_per_page]

            # 写表头
            pdf.set_font("zh", "B", 9)
            _write_row_with_wrap(pdf, headers, col_widths, is_header=True)

            # 写数据行
            pdf.set_font("zh", "", 7)
            for row in chunk:
                _write_row_with_wrap(pdf, row, col_widths, is_header=False)

            pdf.ln(3)

    def _write_row_with_wrap(pdf, cells, widths, is_header=False):
        """写一行：每个 cell 用 multi_cell 做换行，高度取最大高度。"""
        max_lines = 1
        cell_texts = []
        for i, (cell, w) in enumerate(zip(cells, widths)):
            text = str(cell)
            if not is_header and len(text) > 50:
                text = text[:50] + "..."  # 截断超长 reasoning，PDF 空间有限
            # 估算行数
            char_w = pdf.get_string_width("测") if is_header else pdf.get_string_width("测") * 0.9
            lines = max(1, int(pdf.get_string_width(text) / max(w - 2, char_w)) + 1)
            lines = min(lines, 4)  # 最多 4 行
            max_lines = max(max_lines, lines)
            cell_texts.append((text, lines))

        row_h = max_lines * (8 if is_header else 6)

        # 先画所有 cell 的边框
        x_start = pdf.get_x()
        y_start = pdf.get_y()

        for i, ((text, _), w) in enumerate(zip(cell_texts, widths)):
            pdf.rect(x_start + sum(widths[:i]), y_start, w, row_h)

        # 填文字
        for i, ((text, _), w) in enumerate(zip(cell_texts, widths)):
            pdf.set_xy(x_start + sum(widths[:i]) + 1, y_start + 1)
            pdf.multi_cell(w - 2, 6 if is_header else 5, text, align="L")

        pdf.set_xy(x_start, y_start + row_h)

    # === 封面 ===
    pdf.set_font("zh", "B", 22)
    pdf.cell(0, 14, "AI Hedge Fund 分析报告", ln=True, align="C")
    write_normal("", 2)
    pdf.set_font("zh", "B", 10)
    pdf.cell(0, 8, "AI Hedge Fund (WorkBuddy Edition @Tsukimori)", ln=True, align="C")
    pdf.ln(4)
    write_normal(f"生成时间: {run_time}")
    write_normal(f"分析标的: {', '.join(tickers)}")
    write_normal(f"分析师数量: {len(agent_keys)} 位")
    pdf.ln(6)

    # === 摘要 ===
    write_title("一、最终决策摘要", 15)
    summary_rows = []
    for t in tickers:
        d = decisions.get(t, {})
        summary_rows.append([
            t, d.get("action", "-").upper(), str(d.get("quantity", 0)),
            f"{d.get('confidence', 0)}%", d.get("reasoning", "-")[:60]
        ])
    write_table_safe(["股票", "操作", "数量", "置信度", "理由"], summary_rows,
                     [28, 16, 16, 16, pdf.w - 76])

    # === 信号矩阵 ===
    write_title("二、分析师信号矩阵", 15)
    matrix_rows = []
    for t in tickers:
        for ak in agent_keys:
            s = signals.get(ak, {}).get(t, {})
            matrix_rows.append([
                t, ak, s.get("signal", "-").upper(),
                str(s.get("confidence", 0)), s.get("reasoning", "-")[:60]
            ])
    write_table_safe(["股票", "分析师", "信号", "置信度", "推理"], matrix_rows,
                     [24, 38, 16, 16, pdf.w - 94], max_rows_per_page=25)

    # === 风险 ===
    write_title("三、风险与仓位数据", 15)
    risk_rows = []
    for t in tickers:
        r = risk.get(t, {})
        vol = r.get("volatility_metrics", {})
        risk_rows.append([
            t, str(r.get("current_price", "-")),
            f"{r.get('remaining_position_limit', 0):,.0f}",
            f"{vol.get('annualized_volatility', 0):.1%}",
            str(vol.get("data_points", 0))
        ])
    write_table_safe(["股票", "价格", "仓位上限", "年化波动", "数据天数"], risk_rows,
                     [30, 30, 40, 30, pdf.w - 130])

    # === 免责 + 署名 ===
    pdf.ln(4)
    pdf.set_font("zh", "", 8)
    pdf.multi_cell(0, 5,
        "免责声明: 本报告由 AI Hedge Fund Skill (WorkBuddy Edition @Tsukimori) 自动生成，"
        "所有交易建议仅用于研究和教育目的，不构成投资建议。"
        "过去表现不代表未来结果。真实交易前请咨询持牌投资顾问。使用者自负盈亏。")

    write_signature()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)
    return output_path


def main():
    p = argparse.ArgumentParser(description="从 run_fund.json 生成 PDF 报告")
    p.add_argument("--input", required=True, help="run_fund.py 输出的 JSON 文件")
    p.add_argument("--output", help="输出 PDF 路径（默认 report_<timestamp>.pdf）")
    p.add_argument("--html", action="store_true", help="强制生成 HTML 而不是 PDF")
    args = p.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = args.output or f"results/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    if args.html or not HAS_FPDF:
        out_path = generate_html_report(data, output.replace(".pdf", ".html"))
    else:
        out_path = generate_pdf_report(data, output)

    print(f"[report] 报告已生成: {out_path}")


if __name__ == "__main__":
    main()
